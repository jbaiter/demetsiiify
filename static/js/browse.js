/** Global event bus for the browsing interface **/
var bus = new Vue();

Vue.component('CollectionDisplay', {
  props: ['collection'],
  data: function() {
    return {
      'isActive': false,
      'subCollections': []
    };
  },
  template: `
    <li>
      <a @click="onClick" :class="{'is-active': isActive}">
        {{ collection.label }}
        <span class="tag is-light">
          {{ collection.total }}
        </span>
      </a>
      <ul class="menu-list" v-if="shouldShowChildren">
        <CollectionDisplay v-for="subCollection in subCollections"
                          :collection="subCollection" />
      </ul>
    </li>`,
  methods: {
    shouldShowChildren: function() {
      return this.isActive && this.subCollections;
    },
    onClick: function() {
      var vm = this;
      bus.$emit('fetching-page');
      axios.get(this.collection.first)
        .then(function(response) {
          bus.$emit('show-page', response.data);
          if (response.data.collections) {
            vm.subCollections.concat(response.data.collections);
          }
        });
    },
    onShowPage: function(page) {
      if (page.within === this.collection['@id']) {
        this.isActive = true;
        if (page.collections) {
          this.subCollections = page.collections;
        }
      } else {
        this.isActive = false;
      }
    }
  },
  mounted: function() {
    bus.$on('show-page', this.onShowPage);
  }
});


Vue.component('Pagination', {
  props: ['page'],
  template: `
    <nav class="pagination is-centered">
      <a class="pagination-previous" @click="onPrevious"
         :class="{'is-disabled': !page.prev}">
        Previous
      </a>
      <span class="page-indicator">
        {{ page.startIndex + 1 }} - {{ pageEndIndex }} / {{ page.total }}
      </span>
      <a class="pagination-next" @click="onNext"
         :class="{'is-disabled': !page.next}">
        Next
      </a>
    </nav>`,
  methods: {
    onNext: function() {
      axios.get(this.page.next)
        .then(function(response) {
          bus.$emit('show-page', response.data);
        });
    },
    onPrevious: function() {
      axios.get(this.page.prev)
        .then(function(response) {
          bus.$emit('show-page', response.data);
        });
    }
  },
  computed: {
    pageEndIndex: function() {
      return this.page.startIndex + this.page.manifests.length;
    }
  }
});


Vue.component('PageDisplay', {
  props: ['page'],
  template: `
    <div class="current-page">
      <Pagination :page="page" />
      <div class="container columns is-multiline">
        <ManifestView v-for="manifest in page.manifests"
                      :manifest="manifest" width="6"/>
      </div>
      <Pagination :page="page" />
    </div>`,
});

var app = new Vue({
  data: {
    rootCollection: window.rootCollection,
    currentPage: window.currentPage
  },
  template: `
    <div class="container browse">
      <div class="columns">
        <div class="column is-3">
          <aside class="menu">
            <ul class="menu-list">
              <CollectionDisplay v-if="rootCollection"
                                 :collection="rootCollection" />
              <li v-else class="collection-loading">Loading</li>
            </ul>
          </aside>
        </div>
        <div class="column">
          <h1 class="title has-text-centered">{{ currentPage.label }}</h1>
          <hr>
          <PageDisplay v-if="currentPage" :page="currentPage" />
        </div>
      </div>
    </div>`,
  mounted: function() {
    var vm = this;
    // Bind events
    bus.$on('show-page', this.onPageChange);

    // Load initial data if not present
    if (!this.rootCollection) {
      axios.get('/iiif/collection/index/top')
        .then(function(response) {
          vm.rootCollection = response.data;
        });
    }
    if (!this.currentPage) {
      axios.get('/iiif/collection/index/p1')
        .then(function(response) {
          bus.$emit('show-page', response.data);
        });
    } else{
      bus.$emit('show-page', this.currentPage);
    }
  },
  methods: {
    onPageChange: function(page) {
      this.currentPage = page;
    }
  }
});

app.$mount('.browse');
